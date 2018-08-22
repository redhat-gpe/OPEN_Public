#!/opt/rh/ruby200/root/usr/bin/ruby

require 'rubygems'
require 'rest_client'
require 'json'

if ARGV[0] == nil
  puts "Please specify a ephemeral token."
  exit 1
else
  $ephTok = ARGV[0]
end

vmJsonFile = File.read('/etc/ravello/vm.json')
vmJsonHash = JSON.parse(vmJsonFile)
$appID = vmJsonHash['appId']

system("/usr/bin/pkill -f -9 ravellobmc.py")

def restCall(call,uri)
  case call
  when 'get'
    RestClient.get(uri, :content_type => :json, :accept => :json, :'X-Ephemeral-Token-Authorization' => $ephTok ){ |response, request, result| response }
  end
end

uri = "https://cloud.ravellosystems.com/api/v1/applications/#{$appID}"
data = restCall("get",uri)
if data.code != 200
  puts "Warning, application ID #{$appID} is not in Ravello."
else
  app = JSON.parse(data)
  appname = app['name']
  app['deployment']['vms'].sort_by{| vm | vm['name']}.each do | vm |
    unless vm['description'].nil?
      ipmiaddr = ""
      ipmipw = ""
      vm['description'].each_line do |line|
        line = line.chomp
        if line =~ /^ipmiaddr:/
          lsp = line.split(':')
          ipmiaddr = lsp[1]
        elsif line =~ /^ipmipw:/
          lsp = line.split(':')
          ipmipw = lsp[1]
        end
      end
      if ipmiaddr != "" && ipmipw != ""
        vmname = vm['name']
        puts "VM Name: (#{vmname}) IPMI IP: (#{ipmiaddr}) IPMI PW: (#{ipmipw})"
      	system("/usr/sbin/ip address add #{ipmiaddr} dev eth0")
        system("/usr/local/bin/ravellobmc.py --app-name=\"#{appname}\" --vm-name=\"#{vmname}\" --aspect=deployment --address=#{ipmiaddr} --ipmi-password #{ipmipw} --api-username=token --api-password=#{$ephTok} &")
        #system("/usr/local/bin/ravellobmc.py --debug --app-name=\"#{appname}\" --vm-name=\"#{vmname}\" --aspect=deployment --address=#{ipmiaddr} --ipmi-password #{ipmipw} --api-username=token --api-password=#{$ephTok} &")
      end
    end
  end
end
